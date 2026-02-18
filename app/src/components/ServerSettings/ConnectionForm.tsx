import { zodResolver } from '@hookform/resolvers/zod';
import { useEffect } from 'react';
import { useForm } from 'react-hook-form';
import * as z from 'zod';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { Input } from '@/components/ui/input';
import { Checkbox } from '@/components/ui/checkbox';
import { useToast } from '@/components/ui/use-toast';
import { apiClient } from '@/lib/api/client';
import { useServerStore } from '@/stores/serverStore';
import { usePlatform } from '@/platform/PlatformContext';

const connectionSchema = z.object({
  serverUrl: z.string().url('Please enter a valid URL'),
  apiKey: z.string().optional(),
});

type ConnectionFormValues = z.infer<typeof connectionSchema>;

export function ConnectionForm() {
  const platform = usePlatform();
  const serverUrl = useServerStore((state) => state.serverUrl);
  const setServerUrl = useServerStore((state) => state.setServerUrl);
  const apiKey = useServerStore((state) => state.apiKey);
  const setApiKey = useServerStore((state) => state.setApiKey);
  const keepServerRunningOnClose = useServerStore((state) => state.keepServerRunningOnClose);
  const setKeepServerRunningOnClose = useServerStore((state) => state.setKeepServerRunningOnClose);
  const { toast } = useToast();

  const form = useForm<ConnectionFormValues>({
    resolver: zodResolver(connectionSchema),
    defaultValues: {
      serverUrl: serverUrl,
      apiKey: apiKey,
    },
  });

  // Sync form with store when settings change externally
  useEffect(() => {
    form.reset({ serverUrl, apiKey });
  }, [serverUrl, apiKey, form]);

  const { isDirty } = form.formState;

  async function onSubmit(data: ConnectionFormValues) {
    setServerUrl(data.serverUrl);
    setApiKey((data.apiKey || '').trim());
    apiClient.resetConnectionCaches();
    form.reset(data); // Reset form state after successful submission
    try {
      await apiClient.getCapabilities(true);
      toast({
        title: 'Server URL updated',
        description: `Connected to ${data.serverUrl}`,
      });
    } catch (error) {
      toast({
        title: 'Connection updated',
        description:
          error instanceof Error
            ? `Saved server, but capability check failed: ${error.message}`
            : 'Saved server URL and API key.',
      });
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Server Connection</CardTitle>
      </CardHeader>
      <CardContent>
        <Form {...form}>
          <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              control={form.control}
              name="serverUrl"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>Server URL</FormLabel>
                  <FormControl>
                    <Input placeholder="http://127.0.0.1:17493" {...field} />
                  </FormControl>
                  <FormDescription>Enter the URL of your voicebox backend server</FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="apiKey"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>API Key (optional)</FormLabel>
                  <FormControl>
                    <Input placeholder="VOICEBOX_API_KEY" autoComplete="off" {...field} />
                  </FormControl>
                  <FormDescription>
                    Required for remote backends protected with `VOICEBOX_API_KEY`.
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />

            {isDirty && <Button type="submit">Update Connection</Button>}
          </form>
        </Form>

        <div className="mt-6 pt-6 border-t">
          <div className="flex items-start space-x-3">
            <Checkbox
              id="keepServerRunning"
              checked={keepServerRunningOnClose}
              onCheckedChange={(checked: boolean) => {
                setKeepServerRunningOnClose(checked);
                platform.lifecycle.setKeepServerRunning(checked).catch((error) => {
                  console.error('Failed to sync setting to Rust:', error);
                });
                toast({
                  title: 'Setting updated',
                  description: checked
                    ? 'Server will continue running when app closes'
                    : 'Server will stop when app closes',
                });
              }}
            />
            <div className="space-y-1">
              <label
                htmlFor="keepServerRunning"
                className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70 cursor-pointer"
              >
                Keep server running when app closes
              </label>
              <p className="text-sm text-muted-foreground">
                When enabled, the server will continue running in the background after closing the
                app. Disabled by default.
              </p>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
